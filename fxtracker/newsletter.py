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
from .picks import ADV_SRC_SHORT
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
    if status in (400, 422) and statuses is not None and sts != _OUT_STATUSES:
        # partially_sent was documented on 2026-09-19; were the pinned API
        # version to reject it, the duplicate check would raise and every
        # reader, USD included, would miss the month. Ask again without it.
        print("WARNING: Buttondown rejected the status list (HTTP %s); retrying without "
              "partially_sent" % status)
        sts = _OUT_STATUSES
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
# The two green buttons' labels sit in two spans: Buttondown inlines its
# template CSS into each issue, where a{color:#0069FF!important} turned their
# white text blue on GREEN (the Oct 2026 issue went out that way) and
# a>*{color:inherit!important} takes a single wrapper with it. The inner span is
# out of both rules' reach, so its own white stays.
#
# What else Buttondown does to our markup, and the rules this file keeps
# because of it. The account has used two of its templates: Modern (the
# Nov 1 2026 issue; its rules are read off the delivered mail) and, from
# 2026-11-09, Classic (its rules are read off Buttondown's own preview; no
# issue had gone out in it when this was written). The markup has to arrive
# right in both.
#   * Both: a{color:<accent>!important;text-decoration:underline}, the accent
#     being #0069FF on Nov 1 and GREEN in the Classic preview. Whatever colour
#     we give an <a>, its words arrive in the accent, underlined: the Nov 1
#     photo credits and footer links were bright blue. Every text link is
#     built by _link below, which uses the buttons' two spans.
#   * Modern: p,ul,li{font-size:16px!important;line-height:24px!important} and
#     p,h1-h6{margin:16px 0!important}. A <p> of ours arrives at 16px/24px
#     whatever we wrote, so the small print came out bigger than the cards.
#     Classic: p,div,ul,li{font-size:16px;line-height:1.4em}. Not !important,
#     but it names every <div>, so one with no font-size of its own is 16px
#     whatever its parent says.
#     So text that must keep its size is a <div> with its own font-size,
#     line-height and margin, and the intro is the only <p> left. Every block
#     that holds words (a button's wrapper too) has its own font-size AND
#     line-height: Classic's 1.4em would otherwise set a row's height in one
#     template and the mail app's default in the other.
#   * Modern: div,table,td,p{color:#000}. A block with no colour of its own is
#     painted black, not its parent's colour, so a <div> that holds text sets
#     its own colour.
#   * Classic: img{margin-left:0!important;margin-right:0!important}. An
#     image's side margin is thrown away, which left every flag touching its
#     country's name. No image of ours has one: the gap after a flag is in the
#     text (_name).
#   * Classic has no margin rule for p or h2 (the mail app's default applies),
#     Modern forces 16px 0 on both. The intro <p> and the one <h2> carry their
#     own margin, which is what Classic shows.
# scripts/digest_check.py proofing() holds every render to these.
SMALL = "#666"       # small print; was #888, 3.5:1 on white where 4.5:1 is the usual floor
SMALL_PX = 12        # ... and its size: the footer, the quote's byline, the photo credits
CREDIT = "#6f6f6f"   # the photo credits (the 2026-11-09 review's grey)


def _esc(x):
    return html.escape(str(x))


def _link(href, label, color=GREEN, style="", underline=False):
    """A text link that arrives in `color`: the label sits in two spans with
    the colour on the inner one, out of reach of Buttondown's blue (the note
    above). Our text-decoration:none on the <a> survives Buttondown; where a
    link should be underlined the inner span draws the line, in `color` (left
    to the <a> it would be Buttondown's blue). `href` and `label` are HTML
    already, so escape what needs it first; `style` is more CSS for the <a>
    (a weight). The green buttons are not text links and keep their own
    markup."""
    return ('<a href="%s" style="color:%s;text-decoration:none%s"><span><span style="color:%s%s">%s'
            '</span></span></a>' % (href, color, ";" + style if style else "", color,
                                    ";text-decoration:underline" if underline else "", label))


def _hold(text):
    """`text` (HTML) kept on one line: a date, "re-grade" and "1-year" would
    otherwise break at a hyphen in the small print."""
    return '<span style="white-space:nowrap">%s</span>' % text


def _date(iso):
    """The footer's "Currency data as of" date (YYYY-MM-DD), held on one line
    and written with non-breaking hyphens (U+2011), which look the same: the
    2026-11-12 test send showed it as a blue underlined link on Doug's phone,
    since mail apps turn anything that reads as a date into a calendar link,
    and a date with other hyphens doesn't read as one."""
    return _hold(_esc(iso).replace("-", "‑"))


def _adv_main(v):
    """The edition's main advisory source by its short name ("US State Dept"):
    the government picks.build_variant grades safety on (v.adv_source) and the
    one the footer's grade key names."""
    return ADV_SRC_SHORT.get(v.adv_source, v.adv_source)


def _adv_by(s, v=USD):
    """Whose level a 🛡️ letter is, where it isn't the edition's main source
    (" per Global Affairs Canada": the government that filled a gap in the US
    list). The grade key names the main source once, so a row doesn't repeat
    it; a bare letter must still never read as WanderGrade's own rating."""
    by = s.get("advBy")
    if not by or by == _adv_main(v):
        return ""
    return " <span style='color:%s'>per %s</span>" % (SMALL, _esc(by))


def _grade(score):
    # None = not measured (no climate data for weather): a dash, as on the site.
    if score is None:
        return "—"
    return ("A+" if score >= 93 else "A" if score >= 85 else "B+" if score >= 78
            else "B" if score >= 68 else "C" if score >= 55 else "D" if score >= 42
            else "F")


# The Overall grade is a solid badge in the site's own grade colours:
# public/styles.css, the fills .grAp to .grF and the letter colour under them
# (.gr is white; ".grA, .grBp, .grB, .grC, .grD { color: #000 }", since white
# only clears 4.5:1 on the darkest two fills, A+ and F). test_digest_variants
# reads that file and holds these two tables to it.
GRADE_FILL = {"A+": "#067a23", "A": "#2f9e44", "B+": "#74b816", "B": "#c9a200",
              "C": "#e8590c", "D": "#d9480f", "F": "#b00020"}
GRADE_INK = {"A+": "#ffffff", "A": "#000000", "B+": "#000000", "B": "#000000",
             "C": "#000000", "D": "#000000", "F": "#ffffff"}
# (letter size, line height, padding, corner) of the badge on the top card,
# a compact card and a gem. The site's own pill is 13px, 18px on its Overall.
BADGE_TOP, BADGE_CARD, BADGE_GEM = (16, 22, "1px 9px", 7), (13, 18, "1px 7px", 6), (12, 16, "1px 6px", 5)


def _badge(score, size):
    """The Overall grade as a solid badge. It sits after the name's link, not
    in it, and its letter never wraps (A+ stays one piece). An Overall is
    always a letter; a dash would take the grey of the site's .grx."""
    g = _grade(score)
    px, lh, pad, radius = size
    return ("<span style='display:inline-block;background:%s;color:%s;font-size:%dpx;line-height:%dpx;"
            "font-weight:800;padding:%s;border-radius:%dpx;white-space:nowrap'>%s</span>"
            % (GRADE_FILL.get(g, "#f1f1f1"), GRADE_INK.get(g, SMALL), px, lh, pad, radius, g))


def _vo(v):
    """The link parameter that makes the site grade for this edition's home
    (vo = the "traveling from" country; postApplyShared applies it on any
    page). Only non-USD editions carry it: a euro reader who opens a guide
    link in their mail app's browser (no saved fx_origin there) otherwise
    lands on US-graded letters, and the email's letters stop matching the
    page they link to. On the site it is view-only (app.js sharedOriginView,
    the shared-Visited rule): a French reader sees the EUR edition's home,
    Germany, and keeps their own setting. USD links stay exactly as they were."""
    return "" if v.code == "USD" else "&vo=" + v.home_iso


def _guide_url(iso, month, v=USD):
    return "{0}/?tab=guide&gc={1}&vmn={2}{3}".format(SITE, iso, month, _vo(v))


def _flag_img(iso):
    # Real PNG flags render everywhere (incl. Windows/Outlook, where emoji flags
    # collapse to letter-boxes). flagcdn serves free country-code flags.
    # No side margin: Buttondown's Classic template zeroes an image's (the
    # note above _link). _name puts the gap to the country's name in the text.
    return ("<img src='https://flagcdn.com/32x24/{0}.png' width='22' height='16' "
            "alt='{1}' style='vertical-align:-2px;border-radius:2px'>"
            .format(_esc(iso.lower()), _esc(iso)))


def _name(s, g, weight, badge):
    """A card's or gem's name row: the flag, the country's name linking to
    its guide `g`, and the Overall badge.

    The flag's gap is a non-breaking space, which every mail app keeps,
    widened by 3px on the link to the 7px the cards were drawn with (the
    flag's own margin-right, until Classic threw it away). The space sets
    the gap; it does not hold the flag to the name. In a column narrower
    than flag + name a browser still breaks the line after the flag, which
    is how it avoids pushing the card wider. That was seen only in the
    Modern template on a 360 to 375px phone, whose frames left a compact
    card's words 98 to 113px ("Philippines" alone under its flag); with
    the padding below (PANEL_PAD, CARD_PAD) the column is 118px and up and
    none of the USD edition's 12 frozen months shows it from 360px. Don't
    glue the flag to the name with a nowrap span: where the two don't fit,
    the name then runs past the card's edge (tried: about 20px over on a
    320px screen in Modern, 18px at 360px with the old padding). The space
    before the badge is an ordinary one for the same reason: where a name
    fills its line the badge drops to the next, whole. Were the row one
    unbreakable run, a narrow card (110px of photo beside it on a 360px
    phone) would be pushed wider than the screen."""
    return "%s&nbsp;%s %s" % (
        _flag_img(s["iso"]), _link(g, _esc(s["name"]), style="font-weight:%d;margin-left:3px" % weight),
        _badge(s["value"], badge))


def _acts(s):
    labels = [a if isinstance(a, str) else a.get("t", "") for a in (s.get("activities") or [])]
    return [x for x in labels if x][:2]


# ---- the four grades ----------------------------------------------------------
# One grade is its icon, its name on the top card, and its letter, joined
# with non-breaking spaces so no mail app parts an icon from its letter. Two
# grades are parted by "&nbsp;&middot; ": the one place the row may break is
# after a dot.
_SEP = "&nbsp;&middot; "


def _unit(icon, letter, word=""):
    return "%s&nbsp;%s<b>%s</b>" % (icon, word + "&nbsp;" if word else "", letter)


def _grades(s, v=USD, month=None):
    """Affordability, Safety, Weather and Flights as one row. With `month`
    (1-12) it is the top card's: each grade is named and the fare's basis
    follows Flights. Without, a compact card's or a gem's: letters only, and
    the safety letter names its government only where that isn't the
    edition's main source (_adv_by)."""
    top = month is not None
    word = (lambda w: w) if top else (lambda w: "")
    units = [_unit("\U0001f4b0", _grade(s["afford"]), word("Affordability")),
             _unit("\U0001f6e1️", _FLAG.get(s["advLvl"], "B"), word("Safety")) + ("" if top else _adv_by(s, v)),
             _unit("\U0001f324️", _grade(s["wx"]), word("Weather"))]
    # Flights is in the Overall whenever there is fare data, so every row that
    # shows the Overall shows it too.
    if s.get("fly") is not None:
        # An estimate (no cached fare for the route yet: picks._score counts
        # it as a typical fare for the distance, a fixed 70, and sets
        # fareEst) is marked "~" before its letter, as the site prints it
        # (app.js: the grey "~B" pill, "Estimated — no cached fare yet").
        # The grade key says what the mark means. Until Dec 2026 the letter
        # stood unmarked, as if a fare had been compared.
        est = bool(s.get("fareEst"))
        fly = _unit("✈️", ("~" if est else "") + _grade(s["fly"]), word("Flights"))
        if top:
            # The grade's basis: the featured month's fare vs the route's own
            # typical, or — where a route has too few cached months — the
            # year-round fare vs a distance-typical one; an estimate says it
            # is one. The month is named ("February vs the route’s usual"):
            # the issue goes out two months ahead, so "this month" read as
            # the month it arrived in. The name comes from _MONTH_SLUGS, not
            # strftime (the machine's locale).
            fly += " <span style='color:#6b7681'>(%s)</span>" % (
                "estimated, no fare yet" if est
                else "%s vs the route’s usual" % _MONTH_SLUGS[month - 1].capitalize()
                if s.get("fly_basis") == "month" else "year-round, for the distance")
        units.append(fly)
    return _SEP.join(units)


def _source_line(s):
    """The top card says whose advisories its safety grade is, in full, under
    the grades ("" when the payload doesn't say)."""
    if not s.get("advBy"):
        return ""
    return ("<div style='font-size:%dpx;line-height:18px;color:%s;margin:2px 0 0'>Safety grade from %s "
            "advisories</div>" % (SMALL_PX, SMALL, _esc(s["advBy"])))


# ---- the two money lines --------------------------------------------------------
# The same two short lines on the top card and the compact cards, price
# first. Neither carries 💰, which in this email means the Affordability grade
# and nothing else: it stands in the grade rows and the grade key only (the
# "On a budget?" line under the gems carried one too until Dec 2026).

def _fx_text(s, v=USD):
    """The WanderGrade hook: after inflation, the reader's money (v.noun_cap,
    the dollar in the USD edition) goes further here than usual. "" under 3%.
    s["fx"] is the inflation-adjusted move against the 1-year average
    (picks.py); nominal strength in a high-inflation country is a crawl, not
    a deal. The grade key in the footer says what "usual" means."""
    fx = s.get("fx")
    if fx is None or fx < 3:
        return ""
    # Math.round, as the site prints it. The last two words are held
    # together: beside a compact card's photo on a phone the line wraps, and
    # "usual" alone on a line under four cards in a row read as a mistake.
    return "%s %s goes ~%d%% further than&nbsp;usual" % (v.fx_emoji, _esc(v.noun_cap), js_round(fx))


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


def _cost_text(s, v=USD):
    """Concrete, data-backed affordability (from the price level vs home: the
    US in the USD edition), in the site's bands and with its rounding
    (plPhrase's Math.round of the raw value). "" without a price level.
    A pricier place says so and no more: until Dec 2026 it added ", but
    graded worth it", a claim about the Overall the badge now makes itself."""
    pl = s.get("pl")
    if not pl:
        return ""
    band = _pl_band(pl)
    if band < 0:
        # ("US levels" is held together, as "than usual" is in _fx_text.)
        return "Prices ~%d%% below %s&nbsp;levels" % (js_round((1 - pl) * 100), _esc(v.levels_adj))
    if band > 0:
        return "Pricier than %s" % _esc(v.vs_place)
    return "Prices about on par with %s" % _esc(v.vs_place)


def _money_lines(s, v=USD, top=False):
    """The price line, then the dollar line where the card has one."""
    px, lh, ink, gap = (14, 21, "#333", 8) if top else (13, 19, "#555", 3)
    cost, fx = _cost_text(s, v), _fx_text(s, v)
    out = ""
    if cost:
        out += "<div style='font-size:%dpx;line-height:%dpx;color:%s;margin:%dpx 0 0'>%s</div>" % (
            px, lh, ink, gap, cost)
    if fx:
        out += ("<div style='font-size:%dpx;line-height:%dpx;color:%s;font-weight:600;margin:%dpx 0 0'>%s</div>"
                % (px, lh, GREEN, 2 if cost else gap, fx))
    return out


def _dont_miss(s):
    labels = _acts(s)
    if not labels:
        return ""
    return ("<div style='font-size:14px;line-height:21px;color:#333;margin:8px 0 0'><b>Don’t miss:</b> %s</div>"
            % _esc(", ".join(labels)))


# ---- photo credits ----------------------------------------------------------
# One block under the closing quote credits every cover; until Dec 2026 each
# card carried its own "Photo: ..." line (11px, and blue in the delivered
# mail). Why one block at the end of the email is enough:
#   * CC BY 2.0 s4(b) and CC BY-SA 3.0 s4(c) let the credit be given "in any
#     reasonable manner". Neither asks for it beside the photo. Each entry
#     leads with its country, so a reader can tell whose photo is whose.
#   * CC BY-SA 4.0 s3(a)(1)(B) asks us to say when a photo was modified. The
#     image service crops every cover to its box (picks._banner, fit=cover),
#     hence "(cropped)".
#   * CC BY 2.0 s4(b) also wants the photographer's credit at least as
#     prominent as any comparable credit. The email's one comparable credit
#     is the closing quote's byline, so the two are the same size (SMALL_PX).
#     Keep them that way.
# An entry is the country, the photographer's name linking to the photo's file
# page (which has the photo's title and its full terms), then the licence's
# name linking to its text. Names are printed as Commons gives them, escaped,
# never tidied. Two entries are parted like two grades ("&nbsp;&middot; ", so
# a line can end with the dot but never start with one), and a linked licence
# name stays on one line ("CC BY-SA 4.0" used to split after "CC" or at its
# hyphen). A photographer's name may wrap: it can be long. A licence without
# a link is plain text and may wrap too.
def _credits(picks):
    """The credits block: one entry for each card that shows a photo, in card
    order. "" when no card shows one."""
    items = []
    for s in picks:
        c = s.get("photo_credit")
        if not (s.get("photo") and c):
            continue
        lic = (_link(_esc(c["license_url"]), _esc(c["license"]), CREDIT, style="white-space:nowrap")
               if c.get("license_url") else _esc(c["license"]))
        items.append("%s: %s, %s" % (_esc(s["name"]), _link(_esc(c["page"]), _esc(c["artist"]), CREDIT), lic))
    if not items:
        return ""
    return ('<div style="font-size:%dpx;line-height:18px;color:%s;text-align:center;margin:12px 0 0">'
            'Photos (cropped) via Wikimedia Commons. %s</div>' % (SMALL_PX, CREDIT, _SEP.join(items)))


# Side padding, in px, of the grey panel and of a compact card's words. They
# were 20 and 14 until Dec 2026. On a 360px phone in the Classic template that
# left the words beside a card's photo 164px, and "Prices ~71% below US
# levels" (about 176px at 13px) and a grade row with two plus letters (about
# 166px) each took two lines on every card. At 14 and 10 the column is 184px
# and both fit on one line (measured in headless Chrome at 360, 375 and 390px,
# in the system font and in Arial); at 390px nothing wraps differently.
# (Then the photo was a fixed 110x84 box. Since 2026-11-12 it is 35% of the
# card, which is the same 110px at 360px in Classic: the note above
# _compact_card.) Don't widen either without measuring at 360px again.
PANEL_PAD, CARD_PAD = 14, 10


def _hero_card(s, month, v=USD):
    # The top card names the featured month beside its fare (_grades), so it
    # can't go without one: no "this month" fallback, the very wording the
    # month replaced.
    if not month:
        raise ValueError("_hero_card: the top card names the featured month; pass month=1-12")
    g = _guide_url(s["iso"], month, v)
    photo = ("<a href='%s'><img src='%s' width='560' alt='%s' style='width:100%%;max-width:560px;"
             "height:220px;object-fit:cover;display:block'></a>" % (g, s["photo"], _esc(s["name"]))
             ) if s.get("photo") else ""
    return """
    <div style="background:#ffffff;border:1px solid #e6e6e6;border-radius:12px;overflow:hidden;margin:0 0 16px">
      %s
      <div style="padding:15px">
        <div style="font-size:20px;line-height:28px;font-weight:800;color:#111">%s</div>
        <div style="font-size:14px;line-height:22px;color:#444;margin:6px 0 0">%s</div>
        %s%s%s
        <div style="font-size:14px;line-height:20px;margin:14px 0 0"><a href="%s" style="display:inline-block;background:%s;color:#fff;text-decoration:none;font-weight:700;font-size:14px;line-height:20px;padding:10px 18px;border-radius:9px"><span><span style="color:#ffffff">See %s’s guide&nbsp;→</span></span></a></div>
      </div>
    </div>""" % (photo, _name(s, g, 800, BADGE_TOP), _grades(s, v, month), _source_line(s),
                 _money_lines(s, v, top=True), _dont_miss(s), g, GREEN, _esc(s["name"]))


# A compact card's photo grows with the card (Doug, 2026-11-12, "A"): on the
# 2026-11-11 test send a desktop mail app showed a lot of white after each
# compact card, the words reaching about 60% across a 600px email and white
# under a fixed 110x84 photo. Phones looked fine and must stay as they are.
#   * The photo's cell takes THUMB_PCT of the card. 35% is the largest share
#     that leaves a 360px phone exactly as before with the longest real text
#     in Arial: at 36% a grade row ending "~B+" takes two lines (measured in
#     headless Chrome, both fonts, with "North Macedonia" and "South Africa"
#     put in as the longest names). At 360px in Classic the cell is 110px,
#     the old box; at 390px 120x92; at 600px 194x148.
#   * min-width:110px holds Buttondown's Modern template, whose frames leave
#     the card narrower, at the old 110px on a 360px phone (measured: the
#     same as before there; Classic at 360 and 600px doesn't reach it).
#   * The image is width:100%, height:auto, so it keeps the crop's own shape
#     (picks.THUMB_W x THUMB_H, the approved 220:168) and needs no
#     object-fit. width/height attributes give its size at a 600px email:
#     Outlook on the desktop ignores a percentage width on an image and
#     uses them.
#   * The words sit in the middle of the photo's height, so a card with a
#     short text column has no white band under its words either.
# Measured at 600px in Classic: the white right of the words fell from 38%
# of the card to 23% (48% to 33% on a card with no dollar line), the white
# under the photo from 52px to none, and the four cards grew from 567px to
# 636px. Don't change the share without measuring 360px again.
THUMB_PCT, THUMB_MIN_W = 35, 110
THUMB_ATTR_W, THUMB_ATTR_H = 194, 148


def _compact_card(s, month, v=USD):
    g = _guide_url(s["iso"], month, v)
    # The photo is the cover's small copy (picks.THUMB_W x THUMB_H), not the
    # top card's 1024x420 banner; a payload without one (built before Dec
    # 2026) falls back to the banner.
    thumb = ("<td width='%d%%' valign='top' style='width:%d%%;min-width:%dpx'><a href='%s'><img src='%s' "
             "width='%d' height='%d' alt='%s' style='display:block;width:100%%;height:auto;border-radius:8px'>"
             "</a></td>" % (THUMB_PCT, THUMB_PCT, THUMB_MIN_W, g, s.get("photo_thumb") or s["photo"],
                            THUMB_ATTR_W, THUMB_ATTR_H, _esc(s["name"]))) if s.get("photo") else ""
    return """
    <table role="presentation" width="100%%" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #e6e6e6;border-radius:12px;margin:0 0 12px">
      <tr>%s
        <td valign="middle" style="padding:11px %dpx">
          <div style="font-size:16px;line-height:24px;font-weight:800;color:#111">%s</div>
          <div style="font-size:13px;line-height:20px;color:#555;margin:3px 0 0">%s</div>
          %s
          <div style="font-size:13px;line-height:19px;margin:5px 0 0">%s</div>
        </td>
      </tr>
    </table>""" % (thumb, CARD_PAD, _name(s, g, 800, BADGE_CARD), _grades(s, v), _money_lines(s, v),
                   _link(g, "See the guide&nbsp;→", style="font-weight:600"))


def _gem_line(s, month, v=USD):
    g = _guide_url(s["iso"], month, v)
    # The four grades sit in one inline-block: where they don't fit beside
    # the name they move to the next line together (on a 360px phone the
    # last one used to drop alone). Not on a row that names another
    # government ("🛡️ A per Global Affairs Canada"): at about 330px it is
    # wider than a 360 or 375px phone's column, so as one piece it took a
    # line of its own, wrapped inside and still left its last grade alone on
    # a third line. That row flows as it always did, two lines at every
    # phone width. The gap before the grades is a non-breaking space and an
    # ordinary one, twice the gap inside a grade: with a single space the
    # Overall badge read as a pair with the 💰 after it. The row can still
    # break at the ordinary space.
    grades = _grades(s, v)
    if not _adv_by(s, v):
        grades = "<span style='display:inline-block'>%s</span>" % grades
    return ("<div style='font-size:14px;line-height:24px;color:#555;margin:0 0 6px'>%s&nbsp; %s</div>"
            % (_name(s, g, 700, BADGE_GEM), grades))


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


# Fixed, not strftime("%B"): that follows the machine's locale.
_MONTH_SLUGS = ("january", "february", "march", "april", "may", "june", "july",
                "august", "september", "october", "november", "december")


def _cheapest_url(month):
    """The site's /cheapest/<month> page (render_cheapest.path_for: lowercase
    English month names). Its year is the month's next occurrence counting
    the current one, so the issue's month, about two months out, is the
    year the page shows."""
    return "%s/cheapest/%s" % (SITE, _MONTH_SLUGS[month - 1])


def _quote_for(year, month):
    """Deterministic by month: every issue gets a different one, and re-rendering
    the same issue gets the same one (a random pick would make the archive lie)."""
    q, who, src = QUOTES[(year * 12 + month) % len(QUOTES)]
    # A <div> carrying the size readers have always seen: this was a 13px <p>,
    # which Buttondown delivered at 16px/24px. The byline is the size of the
    # photo credits under it (SMALL_PX; _credits' note has the reason).
    return (
        '<div style="font-size:16px;line-height:24px;color:#666;font-style:italic;'
        'border-top:1px solid #e0e0e0;margin:16px 0 0;padding:16px 0 0;text-align:center">'
        '“{0}”'
        '<div style="font-size:{3}px;line-height:18px;color:{4};font-style:normal;margin:4px 0 0">'
        '— {1}, <i>{2}</i></div></div>'
    ).format(_esc(q), _esc(who), _esc(src), SMALL_PX, SMALL)


def digest_subject(v, month_name):
    """The issue's subject. A function of the edition and the month alone, so
    send_digest can ask whether an edition already went out even when it
    couldn't be rendered this run. The month leads ("January trips: ..."), as
    the issue features the month two ahead of the one it arrives in.

    Plain ASCII after the leading emoji: find_sent searches Buttondown with
    the non-ASCII taken out, so a ’ or — inside would leave a needle that is
    not in the real subject, the duplicate check would never find the issue,
    and a re-run would mail the list again (test_send_digest 22 checks every
    edition and month)."""
    return "\U0001f9ed %s trips: where your %s goes furthest" % (month_name, v.noun)


def _grade_key(v, mn, flights=True):
    """The footer's key to the grades, one short paragraph (70 words at most).
    Every clause states what the scoring code does; change one only with the
    code it cites. scripts/test_digest_variants.py 8 holds each to every pick
    and gem of every frozen render.

      the badge ... an equal mix of the others
          picks.WEIGHTS gives each of afford, safe, wx and fly the same
          weight, and picks._score's Overall is their weighted mean over the
          ones a place has (a place with no weather or fare data is averaged
          over the rest, hence "the others", not "the four").
      mostly local prices against <home>, partly whether your <money> goes
      further than usual (against its 1-year average, after inflation)
          picks._score: afford = 0.7 x the price level against the edition's
          home (pl = the place's level / the home's) + 0.3 x the currency
          move; the move is rates.compute_favorability's rate now against its
          average over MAX_HISTORY_DAYS (364 days, _span_words' "1-year"),
          made real by pricelevel.real_fx_pct (the inflation gap). The 💵
          lines and the intro say "further than usual" for the same figure.
      the <main source> advisory level (Level 1 = A, Level 2 = B)
      unless another government is named
          _FLAG (picks.SAFE_GRADE) by the level; picks.build_variant leaves
          out Level 3 and picks._score Level 4, so A and B are the only
          letters an issue can show. The source is _adv_main(v); a place
          graded on another government's level says so (_adv_by on a compact
          card or gem, _source_line on the top card).
      <Month>'s usual weather
          picks._score reads climate.json's score for the month: five years
          of daily temperature and rain (fxtracker/build_climate.py; its
          curated list moves a country's "best" months, not these scores).
      the fare against the usual for that route or distance (~ = estimated)
          picks._score: the month's fare against the route's own median
          (month_fare), else the year-round fare against a fare fitted to
          distance (fare_context). A route with no cached fare is counted
          as a typical fare for its distance (a fixed 70) and carries
          fareEst; _grades prints "~" before that letter, as the site does.
          `flights` False (no card has a fare grade: picks found no fare
          data and left Flights out of every Overall) leaves the sentence
          out, as the rows leave ✈️ out.
    """
    # Non-breaking spaces hold each icon to its "is" and each "Level 1 = A"
    # and "~ = estimated" together, so a line never starts with "= B)";
    # "1-year" can't break at its hyphen either.
    return ("<b>Reading the grades:</b> the badge is the Overall grade, an equal mix of the others. "
            "\U0001f4b0&nbsp;is mostly local prices against %s, partly whether your %s goes further than "
            "usual (against its %s average, after inflation). "
            "\U0001f6e1️&nbsp;is the %s advisory level (Level&nbsp;1&nbsp;=&nbsp;A, "
            "Level&nbsp;2&nbsp;=&nbsp;B) unless another government is named. "
            "\U0001f324️&nbsp;is %s’s usual weather.%s"
            % (_esc(v.vs_place), _esc(v.noun), _hold("1-year"), _esc(_adv_main(v)), _esc(mn),
               " ✈️&nbsp;is the fare against the usual for that route or distance "
               "(~&nbsp;=&nbsp;estimated)." if flights else ""))


def render_digest(data):
    """Return (subject, html_body) for the monthly graded-picks email, worded
    for data["variant"]'s reader (digest_variants; USD when absent)."""
    v = VARIANTS[data.get("variant", "USD")]
    mn, yr, m = data["month_name"], data["year"], data["month"]
    picks, gems = data["picks"], data["gems"]
    month_link = "%s/?vmn=%s%s" % (SITE, m, _vo(v))
    # "Pick your travel month" opens Top Picks too: graded for this home.
    pick_link = SITE if v.code == "USD" else "%s/?vo=%s" % (SITE, v.home_iso)
    # Only non-USD editions say how to switch: the public form can't switch
    # anyone (a second subscribe ADDS a tag).
    switch = "" if v.code == "USD" else (
        " Want another currency’s edition? Reply and say which, or change it in your account"
        " on wandergrade.com (sign in with this address).")
    nstrong = sum(1 for s in picks if (s.get("fx") or 0) >= 3)

    subject = digest_subject(v, mn)
    # The inbox snippet: "Plan ahead:", and the featured month by name (two
    # months out, so "this month" read as the month the issue arrived in).
    if nstrong:
        preheader = ("Plan ahead: after inflation, your %s goes further than usual in %d of %s’s picks."
                     % (v.noun, nstrong, mn))
    else:
        preheader = ("Plan ahead: %d destinations graded A+ to F on value, safety, weather and flights for %s."
                     % (len(picks), mn))

    # The first screen is one brand line and one paragraph, then the top
    # card (Dec 2026; before, a masthead with its tagline, a longer intro, a
    # green calendar box and a "Top picks" heading stood above it, and on a
    # phone the first photo began some 380px down, 740px in the Modern
    # template). The 💵 sentence is there only when a pick has the dollar line;
    # its banknote is held to "marks", or at 390px it ended a line alone.
    # "Top picks" is the site's own name for this list, the best of the
    # most-visited countries. (The redesign first wrote "N best-value trips",
    # which claimed too much: the gems are not in the list and often grade
    # higher. No issue went out with it.)
    # Flights is named only when a card has a fare grade: with no fare data
    # picks leaves it out of every Overall and no row shows ✈️ (the hidden
    # preheader, frozen with the subject, still names it).
    flights = any(s.get("fly") is not None for s in picks + gems)
    intro = ("<b>%d top pick%s for %s</b>, graded A+ to F on %s.%s "
             "Going another month? %s"
             % (len(picks), "" if len(picks) == 1 else "s", _esc(mn),
                "money, safety, weather and flights" if flights else "money, safety and weather",
                " %s&nbsp;marks where your %s goes further than usual right now." % (v.fx_emoji, _esc(v.noun))
                if nstrong else "",
                _link(pick_link, "Pick your travel month&nbsp;→", style="font-weight:600")))

    hero = _hero_card(picks[0], m, v) if picks else ""
    rest = "".join(_compact_card(s, m, v) for s in picks[1:])
    ai_callout = ("<div style='background:#eef7f0;border:1px solid #cfe8d6;border-radius:10px;"
                  "padding:12px 14px;margin:2px 0 18px;font-size:14px;line-height:20px;color:#1a5e33'>✨ Open any "
                  "country’s guide and tap <b>Plan with AI</b> for a tailored, month-aware itinerary — "
                  "ChatGPT, Claude, Grok or Perplexity, your call.</div>")
    gems_block = ""
    if gems:
        gems_block = ("<h2 style='font-size:18px;line-height:24px;margin:20px 0 4px;color:#111'>"
                      "\U0001f48e Hidden gems</h2>"
                      "<div style='font-size:13px;line-height:19px;color:#555;margin:0 0 10px'>"
                      "Under-the-radar, high-value spots the crowds miss:</div>"
                      + "".join(_gem_line(s, m, v) for s in gems))

    # The issue month's /cheapest page (its rule and ranking are
    # render_cheapest's, graded from the US): the USD edition only, as the
    # page is US-origin and a euro reader's picks aren't.
    cheap_link = "" if v.code != "USD" else (
        "<div style='font-size:14px;line-height:21px;color:#111;margin:18px 0 0'>"
        "<b>On a budget?</b> %s</div>"
        % _link(_cheapest_url(m), "The cheapest countries to visit in %s&nbsp;→" % _esc(mn),
                style="font-weight:600"))

    small = "font-size:%dpx;line-height:18px;color:%s" % (SMALL_PX, SMALL)
    body = """<div style="display:none;font-size:1px;color:#f4f5f6;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden">%s&#847;&#847;&#847;&#847;&#847;&#847;&#847;&#847;&#847;&#847;</div>
<div style="max-width:600px;margin:0 auto;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#111;background:#f4f5f6;padding:20px %dpx">
  <div style="font-size:20px;line-height:26px;font-weight:800;color:#111;text-align:center;margin:0 0 10px">\U0001f30d WanderGrade</div>
  <p style="font-size:16px;line-height:24px;color:#111;margin:0 0 16px">%s</p>
  %s
  %s
  %s
  %s%s
  <div style="font-size:15px;line-height:20px;text-align:center;margin:22px 0 6px">
    <a href="%s" style="display:inline-block;background:%s;color:#fff;text-decoration:none;font-weight:700;font-size:15px;line-height:20px;padding:12px 22px;border-radius:10px"><span><span style="color:#ffffff">See every country’s grades&nbsp;→</span></span></a>
  </div>
  <div style="font-size:14px;line-height:21px;color:#444;margin:16px 0 0">\U0001f4ac Tell me where you’re headed — just hit reply, or write to %s. I read every message.</div>
  %s
  %s
  <div style="%s;border-top:1px solid #e0e0e0;margin:14px 0 0;padding:14px 0 0">%s</div>
  <div style="%s;margin:8px 0 0">Grades are for %s planning %s travel; set your home country on the site to %s for you.%s Currency data as of %s.</div>
  <div style="%s;margin:8px 0 0"><b>WanderGrade</b> grades every country A+ to F&nbsp;· once a month, no spam&nbsp;· %s&nbsp;· %s</div>
</div>""" % (_esc(preheader), PANEL_PAD, intro, hero, rest,
             ai_callout, gems_block, cheap_link, month_link, GREEN,
             _link("mailto:hello@wandergrade.com", "<b>hello@wandergrade.com</b>", "#444", underline=True),
             _quote_for(yr, m), _credits(picks),
             small, _grade_key(v, mn, flights),
             small, _esc(v.traveler), _esc(mn), _hold("re-grade"), _esc(switch), _date(data["as_of"]),
             small, _link(SITE, "wandergrade.com", SMALL, underline=True),
             _link(UNSUB, "unsubscribe", SMALL, underline=True))

    return subject, body
