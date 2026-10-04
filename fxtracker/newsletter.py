"""Send the monthly digest to a Buttondown newsletter list (handles the
subscriber list, delivery, and unsubscribe for us). Gated on BUTTONDOWN_API_KEY.

Public signups happen via the embedded form on the site (only the public
newsletter username is needed there — no secret). This module is the other half:
pushing our generated digest to all subscribers via the Buttondown API.

render_digest() now returns a self-contained HTML email (Buttondown accepts an
HTML body and wraps it with the unsubscribe/address footer). The {{ unsubscribe_url }}
token is filled by Buttondown on send; the sample-to-self flow substitutes it.
"""

import datetime
import decimal
import html
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from . import rates  # reuse verifying SSL context
from .digest_variants import SEND_ORDER, VARIANTS, by_tag
from .pricelevel import js_round

API = "https://api.buttondown.email/v1/emails"


def api_key():
    return os.environ.get("BUTTONDOWN_API_KEY", "")


def is_configured():
    return bool(api_key())


def _post(url, payload, headers=None):
    return _call("POST", url, payload, headers)


def _call(method, url, payload=None, headers=None):
    hdrs = {
        "Authorization": "Token " + api_key(),
        "Content-Type": "application/json",
        "User-Agent": "fx-tracker/1.0",
    }
    hdrs.update(headers or {})
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=30, context=rates._SSL) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(raw) if raw.strip().startswith("{") else {})
    except urllib.error.HTTPError as e:
        # Buttondown puts the actual reason (a code like email_duplicate or a
        # field error) in the response body; without surfacing it, three
        # scheduled runs failed as a bare "HTTP Error 400" nobody could act on.
        try:
            detail = e.read().decode("utf-8", "replace")[:600]
        except Exception:
            detail = ""
        raise RuntimeError("Buttondown %s: %s" % (e.code, detail or e.reason)) from e


# Every status that means "this issue has gone, or is going, to the list".
# draft is deliberately absent (a preview run must not block the real send),
# and so is errored (a failed publish should be retryable).
_OUT_STATUSES = ("sent", "about_to_send", "scheduled", "in_flight",
                 "throttled", "resending", "paused")
# Variant mode also counts partially_sent (documented: a paused send that then
# reached part of the list). Re-sending such an edition would give its readers
# two copies. The USD-only send keeps the list above, byte for byte, so its
# request stays exactly the one the digest has always made.
VARIANT_OUT_STATUSES = _OUT_STATUSES + ("partially_sent",)
DUPLICATE_WINDOW_DAYS = 25


def find_sent(subject, days=DUPLICATE_WINDOW_DAYS, headers=None, expected=None, statuses=None):
    """The record (a dict: id, subject, status, metadata, filters, ...) of an
    email with this exact subject that was sent (or queued) in the last
    `days` days, else None. Raises if Buttondown can't be asked.

    Why: nothing else stops a second copy. GitHub starts the monthly cron
    3-7 hours late, so a manual 'send' dispatch while it's still queued, or a
    re-run after an ambiguous publish timeout, mailed everyone twice —
    Buttondown happily accepts two emails with the same subject. The subject
    names the featured month and carries no year, so the date window is the
    real key: next year's same-named issue is far outside it.

    `expected` (a currency code, from send_digest's per-currency run) skips a
    record whose metadata.wg_variant names a different edition. `headers`
    adds the API-version pin those runs send, and `statuses` replaces the
    out-statuses (VARIANT_OUT_STATUSES); without them this is the exact
    request the digest has always made."""
    sts = _OUT_STATUSES if statuses is None else tuple(statuses)
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    # Filter on the plain-text part (the subject leads with an emoji, which a
    # server-side contains-match may normalise differently); the exact
    # comparison below does the real matching.
    needle = subject.encode("ascii", "ignore").decode("ascii").strip() or subject
    qs = urllib.parse.urlencode({"status": sts, "subject": needle,
                                 "creation_date__start": since,
                                 "excluded_fields": "body"}, doseq=True)
    status, page = _call("GET", API + "?" + qs, None, headers)
    if status != 200:
        raise RuntimeError("Buttondown email list returned HTTP %s" % status)
    for e in (page or {}).get("results") or []:
        # subject= is a contains-match server side; insist on the exact one.
        if e.get("subject") == subject and e.get("status") in sts:
            md = e.get("metadata")
            wg = md.get("wg_variant") if isinstance(md, dict) else None
            if expected is not None and wg is not None and wg != expected:
                continue
            return e
    return None


def already_sent(subject, days=DUPLICATE_WINDOW_DAYS):
    """The id of an email with this exact subject that was sent (or queued)
    in the last `days` days, else None. Raises if Buttondown can't be asked.
    (find_sent() has the why.)"""
    e = find_sent(subject, days)
    return (e.get("id") or "?") if e else None


def send(subject, body_markdown, draft=False):
    """Create an email. draft=True saves it as a Buttondown draft (preview /
    send-test from the UI); otherwise it sends to the whole list.

    Returns "draft", "sent", or "already-sent" (this subject already went out
    within DUPLICATE_WINDOW_DAYS, so nothing was created). Raises on any
    failure, including a non-2xx that didn't raise an HTTPError, so a caller
    can never report success for an email that didn't go.

    Two steps, per Buttondown's documented flow: create the email as a draft,
    then POST /emails/{id}/publish. Creating with status "about_to_send" in
    one shot used to work (the Jun 18 test) but has returned 400 on every
    scheduled run since Jul 1, while draft creation kept succeeding — so the
    send path now uses the route the docs actually describe."""
    if not draft:
        # Fails closed: if Buttondown can't say whether the issue already
        # went, don't risk mailing the whole list twice — the run goes red
        # and a re-run later is safe.
        dup = already_sent(subject)
        if dup:
            print("Buttondown already has this issue (%s) sent or queued; not sending again."
                  % dup)
            return "already-sent"
    status, created = _post(API, {"subject": subject, "body": body_markdown,
                                  "status": "draft"})
    if status not in (200, 201):
        raise RuntimeError("Buttondown draft create returned HTTP %s" % status)
    if draft:
        return "draft"
    email_id = created.get("id")
    if not email_id:
        raise RuntimeError("Buttondown created the draft but returned no id: %r" % created)
    # Keyed on the draft's id: a retried publish of the same draft replays
    # the first answer instead of acting twice.
    status, _ = _post(API.rstrip("/") + "/" + email_id + "/publish", {},
                      {"X-Idempotency-Key": "wandergrade-publish-" + email_id})
    if status not in (200, 201):
        raise RuntimeError("Buttondown publish returned HTTP %s" % status)
    return "sent"


# ---- per-currency editions (send_digest.py's variant mode) -----------------
# Each non-USD edition goes only to readers holding its currency tag; the
# USD edition goes last, to everyone who holds none of the tags of an edition
# already out this cycle. Buttondown's audience filters reference tags by id
# and need a pinned API version to come back in a known shape, so these calls
# carry VERSION_HDR (the USD-only path never does: it stays today's calls).
API_VERSION = "2026-04-01"
VERSION_HDR = {"X-API-Version": API_VERSION}
_V1 = API.rsplit("/", 1)[0]          # https://api.buttondown.email/v1
TAGS_API = _V1 + "/tags"
SUBSCRIBERS_API = _V1 + "/subscribers"


class SendError(RuntimeError):
    """A failed edition send. at_publish: the failure came at or after the
    publish call, so the email may have gone out anyway (re-check before
    letting the USD edition reach its readers)."""

    def __init__(self, msg, at_publish=False, email_id=None):
        RuntimeError.__init__(self, msg)
        self.at_publish = at_publish
        self.email_id = email_id


def currency_tags(headers=None):
    """{currency code: [tag id, ...]} for every currency-* tag in Buttondown,
    matched case-insensitively (Buttondown doesn't document whether tag names
    are). One id per code is the normal case; two mean someone created a
    duplicate, and that edition then fails closed (its readers get USD).
    A code with no tag has no readers yet. Raises if the list can't be read."""
    out = {}
    url = TAGS_API + "?page_size=1000"
    for _ in range(50):                      # pagination guard
        status, page = _call("GET", url, None, headers)
        if status != 200:
            raise RuntimeError("Buttondown tag list returned HTTP %s" % status)
        for t in (page or {}).get("results") or []:
            code = by_tag(t.get("name"))
            if code and t.get("id"):
                out.setdefault(code, []).append(t["id"])
        url = (page or {}).get("next")
        if not url:
            return out
    raise RuntimeError("Buttondown tag list: too many pages")


def tag_readers(name, headers=None):
    """How many regular (subscribed) readers hold tag `name`, or None when
    Buttondown's answer has no count. Only used to skip an edition nobody
    chose; a wrong 0 sends those readers the USD issue, a wrong >0 creates
    an issue whose filter is still right."""
    qs = urllib.parse.urlencode({"tag": name, "type": "regular"})
    status, page = _call("GET", SUBSCRIBERS_API + "?" + qs, None, headers)
    if status != 200:
        raise RuntimeError("Buttondown subscriber count returned HTTP %s" % status)
    n = (page or {}).get("count")
    return n if isinstance(n, int) else None


def audience(code, tag_ids, exclude):
    """Buttondown `filters` for edition `code`: holds its tag (non-USD) and
    none of the tags of the editions in `exclude` (out, or outcome unknown,
    this cycle). USD has no positive filter: it is everyone else, including
    readers with no currency tag at all."""
    fl = []
    if code != "USD":
        fl.append({"field": "subscriber.tags", "operator": "contains",
                   "value": tag_ids[code][0]})
    for c in SEND_ORDER:
        if c in exclude and c != code:
            for tid in tag_ids.get(c) or []:
                fl.append({"field": "subscriber.tags", "operator": "not_contains", "value": tid})
    return {"predicate": "and", "groups": [], "filters": fl}


def describe_audience(code, exclude):
    """The audience in words, for logs and --dry-run."""
    ex = [c for c in SEND_ORDER if c in exclude and c != code]
    who = "everyone" if code == "USD" else "has " + VARIANTS[code].tag
    if ex:
        who += "; lacks " + ", ".join(VARIANTS[c].tag for c in ex)
    return who


def _norm_filters(f):
    """Comparable form of a filters object: predicate, sorted
    (field, operator, value) triples, normalised groups."""
    if not isinstance(f, dict):
        return None
    return (f.get("predicate"),
            sorted((x.get("field"), x.get("operator"), str(x.get("value")))
                   for x in (f.get("filters") or []) if isinstance(x, dict)),
            sorted(repr(_norm_filters(g)) for g in (f.get("groups") or [])))


def send_variant(subject, body, filters, draft=False, metadata=None, archival_mode=None,
                 headers=None):
    """Create one edition as a draft with an audience filter, check Buttondown
    kept that filter, then (unless `draft`) publish it. Returns the email id.

    The check is the safety net: an old API-version pin, or a plan without
    segmentation, may drop or rewrite `filters`, and publishing that draft
    would mail the whole list. Raises SendError; .at_publish says whether
    the email might have gone out regardless."""
    hdr = dict(VERSION_HDR if headers is None else headers)
    payload = {"subject": subject, "body": body, "status": "draft", "filters": filters}
    if metadata is not None:
        payload["metadata"] = metadata
    if archival_mode is not None:
        payload["archival_mode"] = archival_mode
    try:
        status, created = _call("POST", API, payload, hdr)
    except Exception as e:
        raise SendError("draft create failed: %s" % e)
    if status not in (200, 201):
        raise SendError("Buttondown draft create returned HTTP %s" % status)
    email_id = (created or {}).get("id")
    if not email_id:
        raise SendError("Buttondown created the draft but returned no id: %r" % created)
    if _norm_filters((created or {}).get("filters")) != _norm_filters(filters):
        fate = _defuse_draft(email_id, subject, hdr)
        raise SendError("audience filter dropped/changed by Buttondown (draft %s %s, "
                        "not publishing): sent %r, got %r"
                        % (email_id, fate, filters, (created or {}).get("filters")), email_id=email_id)
    if draft:
        return email_id
    try:
        status, _ = _call("POST", API.rstrip("/") + "/" + email_id + "/publish", {},
                          dict(hdr, **{"X-Idempotency-Key": "wandergrade-publish-" + email_id}))
    except Exception as e:
        raise SendError("publish failed: %s" % e, at_publish=True, email_id=email_id)
    if status not in (200, 201):
        raise SendError("Buttondown publish returned HTTP %s" % status, at_publish=True,
                        email_id=email_id)
    return email_id


DEFUSED_PREFIX = "[DO NOT SEND — audience dropped] "


def _defuse_draft(email_id, subject, headers):
    """Make a draft whose audience filter Buttondown didn't keep impossible to
    send by mistake, and say what happened to it. Such a draft goes to
    whatever audience Buttondown stored, possibly the whole list, and it sits
    in the dashboard with a normal-looking subject one click from Send. It is
    renamed (kept, so the owner can see what Buttondown did with the filter);
    if the rename fails it is deleted; if that fails too, the log says to
    delete it by hand. Never raises."""
    url = API.rstrip("/") + "/" + email_id
    try:
        status, _ = _call("PATCH", url, {"subject": DEFUSED_PREFIX + subject}, headers)
        if status in (200, 201):
            return "renamed '%s...'" % DEFUSED_PREFIX.strip()
    except Exception:
        pass
    try:
        status, _ = _call("DELETE", url, None, headers)
        if status in (200, 202, 204):
            return "deleted"
    except Exception:
        pass
    return "kept AS IS: couldn't rename or delete it — DELETE IT IN BUTTONDOWN, it may mail everyone"


def _span_words(days):
    """Say "1-year", not "364-day". The FX free tier only reaches ~366 days back so
    history caps at 364, and printing that at a reader is precision nobody asked
    for — a day either way cannot change what "vs its average" means. Snap to the
    nearest round span within a week; anything else still prints its day count."""
    for n, word in ((365, "1-year"), (180, "6-month"), (90, "3-month"), (30, "1-month")):
        if abs(days - n) <= 7:
            return word
    return "{0}-day".format(days)


def render_markdown(rows, as_of, baseline_days):
    lines = ["The US dollar is favorable vs its {0} average for:".format(_span_words(baseline_days)), ""]
    for r in rows:
        lines.append("- **{code}** ({name}): 1 USD = {rate} {code} — +{pct}% vs avg".format(
            code=r["code"], name=r["name"], rate=r["rate_now"], pct=r["strength_pct"]))
    lines += ["", "_Sent by WanderGrade. Good time to plan a trip._"]
    return "\n".join(lines)


# ---- monthly graded-picks digest -------------------------------------------
# Renders the payload from fxtracker.picks.build() into an HTML email.

_FLAG = {1: "A", 2: "B", 3: "D"}   # safety grade by advisory level (picks.SAFE_GRADE)
USD = VARIANTS["USD"]              # the edition every render defaults to
SITE = "https://wandergrade.com"
UNSUB = "{{ unsubscribe_url }}"    # Buttondown fills this on send
GREEN = "#0a7d28"


def _esc(x):
    return html.escape(str(x))


def _grade(score):
    # None = not measured (no climate data for weather): a dash, as on the site.
    if score is None:
        return "—"
    return ("A+" if score >= 93 else "A" if score >= 85 else "B+" if score >= 78
            else "B" if score >= 68 else "C" if score >= 55 else "D" if score >= 42
            else "F")


def _vo(v):
    """The link parameter that makes the site grade for this edition's home
    (vo = the "traveling from" country; postApplyShared applies it on any
    page). Only non-USD editions carry it: a euro reader who opens a guide
    link in their mail app's browser (no saved fx_origin there) otherwise
    lands on US-graded letters, and the email's letters stop matching the
    page they link to. It also saves that origin on the site, so a French
    reader's own setting becomes Germany's, the home the EUR edition grades
    for. USD links stay exactly as they were."""
    return "" if v.code == "USD" else "&vo=" + v.home_iso


def _guide_url(iso, month, v=USD):
    return "{0}/?tab=guide&gc={1}&vmn={2}{3}".format(SITE, iso, month, _vo(v))


def _flag_img(iso):
    # Real PNG flags render everywhere (incl. Windows/Outlook, where emoji flags
    # collapse to letter-boxes). flagcdn serves free country-code flags.
    return ("<img src='https://flagcdn.com/32x24/{0}.png' width='22' height='16' "
            "alt='{1}' style='vertical-align:-2px;border-radius:2px;margin-right:7px'>"
            .format(_esc(iso.lower()), _esc(iso)))


def _acts(s):
    labels = [a if isinstance(a, str) else a.get("t", "") for a in (s.get("activities") or [])]
    return [x for x in labels if x][:2]


def _fx_line(s, compact=False, v=USD):
    """The WanderGrade hook: after inflation, the reader's money (v.noun, the
    dollar in the USD edition) goes unusually far here.
    s["fx"] is the inflation-adjusted move (picks.py); nominal strength in a
    high-inflation country is a crawl, not a deal."""
    fx = s.get("fx")
    if fx is None or fx < 3:
        return ""
    pct = js_round(fx)   # Math.round, as the site prints it
    if compact:
        return ("<div style='font-size:13px;color:%s;margin:4px 0 0'>%s %s goes ~%d%% "
                "further than its 1-yr average here, after inflation</div>"
                % (GREEN, v.fx_emoji, _esc(v.noun_cap), pct))
    return ("<div style='font-size:14px;color:%s;font-weight:600;margin:8px 0 0'>%s "
            "After inflation, your %s goes about %d%% further here than its 1-year average."
            "</div>" % (GREEN, v.fx_emoji, _esc(v.noun), pct))


# "About the same as home" is one band on the site: within ±10%, judged on the
# two decimals the price level prints with (app.js PL_SAME / plShown / plBand).
# This line used < 0.95 / > 1.1 on the raw value, so a pick at 0.93 said
# "about 7% below US levels" here while the site's Cost table said "about the
# same", and one at 1.104 (printed 1.10) said "pricier" here and "about the
# same" there.
PL_SAME = 0.1


def _pl_shown(pl):
    """The price level as the site prints it: JS rel.toFixed(2), as a number.
    toFixed rounds the float's exact binary value half-up, which is what
    Decimal(pl) + ROUND_HALF_UP does (1.105 is stored a hair under, so it
    prints 1.10 on both sides); '%.2f' would send an exact half to even."""
    return float(decimal.Decimal(pl).quantize(decimal.Decimal("0.01"), rounding=decimal.ROUND_HALF_UP))


def _pl_band(pl):
    """app.js plBand: -1 cheaper, 0 about the same, 1 pricier."""
    r = _pl_shown(pl)
    return -1 if r <= 1 - PL_SAME else 0 if r <= 1 + PL_SAME else 1


def _cost_line(s, compact=False, v=USD):
    """Concrete, data-backed affordability (from the price level vs home: the
    US in the USD edition), in the site's bands and with its rounding
    (plPhrase's Math.round of the raw value)."""
    pl = s.get("pl")
    if not pl:
        return ""
    band = _pl_band(pl)
    if band < 0:
        txt = "prices run about %d%% below %s levels" % (js_round((1 - pl) * 100), _esc(v.levels_adj))
    elif band > 0:
        # "but graded worth it" claims the Overall makes up for the prices.
        # In the INR edition every pick is Affordability F and C overall, so
        # the hero read "Everyday pricier than India, but graded worth it"
        # over a C. Other editions say it only at B or better (68+); USD
        # keeps its wording exactly.
        worth = v.code == "USD" or (s.get("value") or 0) >= 68
        txt = "pricier than %s%s" % (_esc(v.vs_place), ", but graded worth it" if worth else "")
    else:
        txt = "prices about on par with %s" % _esc(v.vs_place)
    if compact:
        return "<div style='font-size:13px;color:#555;margin:4px 0 0'>\U0001f4b0 %s</div>" % (
            txt[0].upper() + txt[1:])
    return "<div style='font-size:14px;color:#333;margin:6px 0 0'>\U0001f4b0 Everyday %s.</div>" % txt


def _value_line(s, compact=False, v=USD):
    """Lead with the FX hook when it's strong, else the cost anchor."""
    return _fx_line(s, compact, v) or _cost_line(s, compact, v)


def _dont_miss(s):
    labels = _acts(s)
    if not labels:
        return ""
    return ("<div style='font-size:14px;color:#333;margin:8px 0 0'><b>Don’t miss:</b> %s</div>"
            % _esc(", ".join(labels)))


def _credit(s):
    """CC BY / BY-SA require the author and licence next to the image."""
    c = s.get("photo_credit")
    if not c:
        return ""
    lic = ("<a href='%s' style='color:#888'>%s</a>" % (_esc(c["license_url"]), _esc(c["license"]))
           if c.get("license_url") else _esc(c["license"]))
    return ("<div style='font-size:11px;color:#888;margin:4px 0 0'>Photo: <a href='%s' "
            "style='color:#888'>%s</a> &middot; %s</div>" % (_esc(c["page"]), _esc(c["artist"]), lic))


def _fly(s, compact=False):
    # Flights is in the Overall whenever there is fare data, so every line that
    # shows the Overall shows it too (the gem lines used to leave it out).
    if s.get("fly") is None:
        return ""
    # The grade's basis, in the hero line: the featured month's fare vs the
    # route's own typical, or — where a route has too few cached months —
    # the year-round fare vs a distance-typical one.
    basis = "" if compact else (" <span style='color:#6b7681'>(%s)</span>"
                                % ("this month vs the route's usual" if s.get("fly_basis") == "month"
                                   else "year-round, for the distance"))
    return ((" &middot; ✈️ %s" if compact else " &nbsp;&middot;&nbsp; ✈️ Flights <b>%s</b>%s")
            % ((_grade(s["fly"]),) if compact else (_grade(s["fly"]), basis)))


def _hero_card(s, month, v=USD):
    g = _guide_url(s["iso"], month, v)
    photo = ("<a href='%s'><img src='%s' width='560' alt='%s' style='width:100%%;max-width:560px;"
             "height:220px;object-fit:cover;display:block'></a>" % (g, s["photo"], _esc(s["name"]))
             ) if s.get("photo") else ""
    return """
    <div style="background:#ffffff;border:1px solid #e6e6e6;border-radius:12px;overflow:hidden;margin:0 0 16px">
      %s
      <div style="padding:15px">
        <div style="font-size:20px;font-weight:800;color:#111">%s<a href="%s" style="color:%s;text-decoration:none">%s</a> <span style="color:#666">— Overall %s</span></div>
        <div style="font-size:14px;color:#444;margin:5px 0 0">\U0001f4b0 Affordability <b>%s</b> &nbsp;&middot;&nbsp; \U0001f6e1️ Safety <b>%s</b> &nbsp;&middot;&nbsp; \U0001f324️ Weather <b>%s</b>%s</div>
        %s%s%s%s
        <div style="margin:14px 0 0"><a href="%s" style="display:inline-block;background:%s;color:#fff;text-decoration:none;font-weight:700;font-size:14px;padding:10px 18px;border-radius:9px">See %s’s guide →</a></div>
      </div>
    </div>""" % (photo, _flag_img(s["iso"]), g, GREEN, _esc(s["name"]), _grade(s["value"]),
                 _grade(s["afford"]), _FLAG.get(s["advLvl"], "B"), _grade(s["wx"]), _fly(s),
                 _fx_line(s, v=v), _cost_line(s, v=v), _dont_miss(s), _credit(s), g, GREEN,
                 _esc(s["name"]))


def _compact_card(s, month, v=USD):
    g = _guide_url(s["iso"], month, v)
    thumb = ("<td width='110' valign='top'><a href='%s'><img src='%s' width='110' alt='%s' "
             "style='width:110px;height:84px;object-fit:cover;border-radius:8px;display:block'></a></td>"
             % (g, s["photo"], _esc(s["name"]))) if s.get("photo") else ""
    return """
    <table role="presentation" width="100%%" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #e6e6e6;border-radius:12px;margin:0 0 12px">
      <tr>%s
        <td valign="top" style="padding:11px 14px">
          <div style="font-size:16px;font-weight:800;color:#111">%s<a href="%s" style="color:%s;text-decoration:none">%s</a> <span style="color:#666">— %s</span></div>
          <div style="font-size:13px;color:#555;margin:3px 0 0">\U0001f4b0 %s &middot; \U0001f6e1️ %s &middot; \U0001f324️ %s%s</div>
          %s%s
          <div style="font-size:13px;margin:6px 0 0"><a href="%s" style="color:%s;text-decoration:none;font-weight:600">See the guide →</a></div>
        </td>
      </tr>
    </table>""" % (thumb, _flag_img(s["iso"]), g, GREEN, _esc(s["name"]), _grade(s["value"]),
                   _grade(s["afford"]), _FLAG.get(s["advLvl"], "B"), _grade(s["wx"]),
                   _fly(s, compact=True), _value_line(s, compact=True, v=v), _credit(s), g, GREEN)


def _gem_line(s, month, v=USD):
    g = _guide_url(s["iso"], month, v)
    return ("<div style='font-size:14px;margin:0 0 9px;color:#111'>%s<a href='%s' "
            "style='color:%s;text-decoration:none;font-weight:700'>%s</a> "
            "<span style='color:#666'>— %s &middot; \U0001f4b0 %s &middot; \U0001f6e1️ %s "
            "&middot; \U0001f324️ %s%s</span></div>") % (
        _flag_img(s["iso"]), g, GREEN, _esc(s["name"]), _grade(s["value"]),
        _grade(s["afford"]), _FLAG.get(s["advLvl"], "B"), _grade(s["wx"]), _fly(s, compact=True))


# One line of human at the end of a page of grades. Every author here died long
# before 1929, so the text is public domain and safe to print — and every quote is
# cited to the work it's actually from.
#
# That sourcing is the point, not pedantry. The best-known travel quotes are mostly
# misattributed: "the world is a book and those who do not travel read only one
# page" is not Augustine, "twenty years from now you will be more disappointed by
# the things you didn't do" is not Twain, and "travel is the only thing you buy
# that makes you richer" has no author at all. A site that grades transparently
# cannot print a confident citation it hasn't checked. If you add to this list,
# add the work — and if you can't name the work, don't add the quote.
QUOTES = [
    ("Travel is fatal to prejudice, bigotry, and narrow-mindedness.",
     "Mark Twain", "The Innocents Abroad, 1869"),
    ("I travel not to go anywhere, but to go. I travel for travel’s sake.",
     "Robert Louis Stevenson", "Travels with a Donkey in the Cévennes, 1879"),
    ("Though we travel the world over to find the beautiful, "
     "we must carry it with us, or we find it not.",
     "Ralph Waldo Emerson", "Essays: First Series, 1841"),
    ("I am tormented with an everlasting itch for things remote.",
     "Herman Melville", "Moby-Dick, 1851"),
    ("The mountains are calling and I must go.",
     "John Muir", "letter to his sister Sarah, 1873"),
]


def _quote_for(year, month):
    """Deterministic by month: every issue gets a different one, and re-rendering
    the same issue gets the same one (a random pick would make the archive lie)."""
    q, who, src = QUOTES[(year * 12 + month) % len(QUOTES)]
    return (
        '<p style="font-size:13px;line-height:1.6;color:#666;font-style:italic;'
        'border-top:1px solid #e0e0e0;margin:20px 0 0;padding-top:16px;text-align:center">'
        '“{0}”<br>'
        '<span style="font-style:normal;color:#888">— {1}, <i>{2}</i></span></p>'
    ).format(_esc(q), _esc(who), _esc(src))


def digest_subject(v, month_name):
    """The issue's subject. A function of the edition and the month alone, so
    send_digest can ask whether an edition already went out even when it
    couldn't be rendered this run."""
    return "\U0001f9ed Where your %s goes furthest this %s" % (v.noun, month_name)


def render_digest(data):
    """Return (subject, html_body) for the monthly graded-picks email, worded
    for data["variant"]'s reader (digest_variants; USD when absent)."""
    v = VARIANTS[data.get("variant", "USD")]
    mn, yr, m = data["month_name"], data["year"], data["month"]
    picks, gems = data["picks"], data["gems"]
    month_link = "%s/?vmn=%s%s" % (SITE, m, _vo(v))
    # "Pick your travel month" opens Top Picks too: graded for this home.
    pick_link = SITE if v.code == "USD" else "%s/?vo=%s" % (SITE, v.home_iso)
    # Only non-USD editions say how to switch: USD's text is frozen, and the
    # public form can't switch anyone (a second subscribe ADDS a tag).
    switch = "" if v.code == "USD" else (
        " Want another currency’s edition? Reply and say which, or change it in your account"
        " on wandergrade.com (sign in with this address).")
    nstrong = sum(1 for s in picks if (s.get("fx") or 0) >= 3)

    subject = digest_subject(v, mn)
    if nstrong:
        preheader = ("After inflation, your %s goes further than usual in %d of this "
                     "month’s picks — here’s where it’s worth going." % (v.noun, nstrong))
    else:
        preheader = ("%d destinations graded A+ to F on value, safety, weather and flights this %s."
                     % (len(picks), mn))

    hero = _hero_card(picks[0], m, v) if picks else ""
    rest = "".join(_compact_card(s, m, v) for s in picks[1:])
    ai_callout = ("<div style='background:#eef7f0;border:1px solid #cfe8d6;border-radius:10px;"
                  "padding:12px 14px;margin:2px 0 18px;font-size:14px;color:#1a5e33'>✨ <b>New:</b> "
                  "open any country’s guide and tap <b>Plan with AI</b> for a tailored, month-aware "
                  "itinerary — ChatGPT or Claude, your call.</div>")
    gems_block = ""
    if gems:
        gems_block = ("<h2 style='font-size:18px;margin:20px 0 4px;color:#111'>\U0001f48e Hidden gems</h2>"
                      "<p style='font-size:13px;color:#555;margin:0 0 12px'>Under-the-radar, high-value "
                      "spots the crowds miss:</p>" + "".join(_gem_line(s, m, v) for s in gems))

    body = """<div style="display:none;font-size:1px;color:#f4f5f6;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden">%s&#847;&#847;&#847;&#847;&#847;&#847;&#847;&#847;&#847;&#847;</div>
<div style="max-width:600px;margin:0 auto;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#111;background:#f4f5f6;padding:20px">
  <div style="text-align:center;margin:0 0 18px">
    <div style="font-size:22px;font-weight:800;color:#111">\U0001f30d WanderGrade</div>
    <div style="font-size:14px;color:#555">Where Should I Travel Next?</div>
  </div>
  <p style="font-size:15px;line-height:1.5;color:#111">Where’s worth it in <b>%s %s</b>? WanderGrade grades every country <b>A+ to F</b> on what your trip actually hinges on — how far your money goes, safety, weather and flights. The twist: we flag where <b>your %s is unusually strong right now</b>. This month’s standouts \U0001f447</p>
  <p style="font-size:13px;color:#555;background:#eef7f0;border-radius:8px;padding:10px 12px">\U0001f4c5 Featured for <b>%s</b> — about two months out, the sweet spot for booking. Going a different time? <a href="%s" style="color:%s;font-weight:600;text-decoration:none">Pick your travel month →</a></p>
  <h2 style="font-size:18px;margin:22px 0 10px;color:#111">\U0001f31f Top picks</h2>
  %s
  %s
  %s
  %s
  <div style="text-align:center;margin:22px 0 6px">
    <a href="%s" style="display:inline-block;background:%s;color:#fff;text-decoration:none;font-weight:700;font-size:15px;padding:12px 22px;border-radius:10px">See every country’s grades →</a>
  </div>
  <p style="font-size:13px;color:#555;margin:16px 0 0">\U0001f4ac Tell me where you’re headed — just hit reply, or write to <a href="mailto:hello@wandergrade.com" style="color:#555"><b>hello@wandergrade.com</b></a>. I read every message.</p>
  %s
  <p style="font-size:12px;color:#888;line-height:1.6;border-top:1px solid #e0e0e0;margin-top:14px;padding-top:14px">
    Grades are for %s planning %s travel; set your home country on the site to re-grade for you.%s Currency data as of %s. Photos via Wikimedia Commons.<br>
    <b>WanderGrade</b> · once a month, no spam · <a href="%s" style="color:#888">wandergrade.com</a> · <a href="%s" style="color:#888">unsubscribe</a>
  </p>
</div>""" % (_esc(preheader), _esc(mn), yr, _esc(v.noun), _esc(mn), pick_link, GREEN, hero, rest,
             ai_callout, gems_block, month_link, GREEN, _quote_for(yr, m),
             _esc(v.traveler), _esc(mn), _esc(switch), _esc(data["as_of"]), SITE, UNSUB)

    return subject, body
