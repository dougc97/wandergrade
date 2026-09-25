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
import html
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from . import rates  # reuse verifying SSL context
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
DUPLICATE_WINDOW_DAYS = 25


def already_sent(subject, days=DUPLICATE_WINDOW_DAYS):
    """The id of an email with this exact subject that was sent (or queued)
    in the last `days` days, else None. Raises if Buttondown can't be asked.

    Why: nothing else stops a second copy. GitHub starts the monthly cron
    3-7 hours late, so a manual 'send' dispatch while it's still queued, or a
    re-run after an ambiguous publish timeout, mailed everyone twice —
    Buttondown happily accepts two emails with the same subject. The subject
    names the featured month and carries no year, so the date window is the
    real key: next year's same-named issue is far outside it."""
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    # Filter on the plain-text part (the subject leads with an emoji, which a
    # server-side contains-match may normalise differently); the exact
    # comparison below does the real matching.
    needle = subject.encode("ascii", "ignore").decode("ascii").strip() or subject
    qs = urllib.parse.urlencode({"status": _OUT_STATUSES, "subject": needle,
                                 "creation_date__start": since,
                                 "excluded_fields": "body"}, doseq=True)
    status, page = _call("GET", API + "?" + qs)
    if status != 200:
        raise RuntimeError("Buttondown email list returned HTTP %s" % status)
    for e in (page or {}).get("results") or []:
        # subject= is a contains-match server side; insist on the exact one.
        if e.get("subject") == subject and e.get("status") in _OUT_STATUSES:
            return e.get("id") or "?"
    return None


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


def _guide_url(iso, month):
    return "{0}/?tab=guide&gc={1}&vmn={2}".format(SITE, iso, month)


def _flag_img(iso):
    # Real PNG flags render everywhere (incl. Windows/Outlook, where emoji flags
    # collapse to letter-boxes). flagcdn serves free country-code flags.
    return ("<img src='https://flagcdn.com/32x24/{0}.png' width='22' height='16' "
            "alt='{1}' style='vertical-align:-2px;border-radius:2px;margin-right:7px'>"
            .format(_esc(iso.lower()), _esc(iso)))


def _acts(s):
    labels = [a if isinstance(a, str) else a.get("t", "") for a in (s.get("activities") or [])]
    return [x for x in labels if x][:2]


def _fx_line(s, compact=False):
    """The WanderGrade hook: after inflation, the dollar goes unusually far here.
    s["fx"] is the inflation-adjusted move (picks.py); nominal strength in a
    high-inflation country is a crawl, not a deal."""
    fx = s.get("fx")
    if fx is None or fx < 3:
        return ""
    pct = js_round(fx)   # Math.round, as the site prints it
    if compact:
        return ("<div style='font-size:13px;color:%s;margin:4px 0 0'>\U0001f4b5 Dollar goes ~%d%% "
                "further than its 1-yr average here, after inflation</div>" % (GREEN, pct))
    return ("<div style='font-size:14px;color:%s;font-weight:600;margin:8px 0 0'>\U0001f4b5 "
            "After inflation, your dollar goes about %d%% further here than its 1-year average."
            "</div>" % (GREEN, pct))


def _cost_line(s, compact=False):
    """Concrete, data-backed affordability (from the price level vs the US)."""
    pl = s.get("pl")
    if not pl:
        return ""
    if pl < 0.95:
        txt = "prices run about %d%% below US levels" % int(round((1 - pl) * 100))
    elif pl > 1.1:
        txt = "pricier than the US, but graded worth it"
    else:
        txt = "prices about on par with the US"
    if compact:
        return "<div style='font-size:13px;color:#555;margin:4px 0 0'>\U0001f4b0 %s</div>" % (
            txt[0].upper() + txt[1:])
    return "<div style='font-size:14px;color:#333;margin:6px 0 0'>\U0001f4b0 Everyday %s.</div>" % txt


def _value_line(s, compact=False):
    """Lead with the FX hook when it's strong, else the cost anchor."""
    return _fx_line(s, compact) or _cost_line(s, compact)


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
    return ((" &middot; ✈️ %s" if compact else " &nbsp;&middot;&nbsp; ✈️ Flights <b>%s</b>")
            % _grade(s["fly"]))


def _hero_card(s, month):
    g = _guide_url(s["iso"], month)
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
                 _fx_line(s), _cost_line(s), _dont_miss(s), _credit(s), g, GREEN, _esc(s["name"]))


def _compact_card(s, month):
    g = _guide_url(s["iso"], month)
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
                   _fly(s, compact=True), _value_line(s, compact=True), _credit(s), g, GREEN)


def _gem_line(s, month):
    g = _guide_url(s["iso"], month)
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


def render_digest(data):
    """Return (subject, html_body) for the monthly graded-picks email."""
    mn, yr, m = data["month_name"], data["year"], data["month"]
    picks, gems = data["picks"], data["gems"]
    month_link = "%s/?vmn=%s" % (SITE, m)
    nstrong = sum(1 for s in picks if (s.get("fx") or 0) >= 3)

    subject = "\U0001f9ed Where your dollar goes furthest this %s" % mn
    if nstrong:
        preheader = ("After inflation, your dollar goes further than usual in %d of this "
                     "month’s picks — here’s where it’s worth going." % nstrong)
    else:
        preheader = ("%d destinations graded A+ to F on value, safety, weather and flights this %s."
                     % (len(picks), mn))

    hero = _hero_card(picks[0], m) if picks else ""
    rest = "".join(_compact_card(s, m) for s in picks[1:])
    ai_callout = ("<div style='background:#eef7f0;border:1px solid #cfe8d6;border-radius:10px;"
                  "padding:12px 14px;margin:2px 0 18px;font-size:14px;color:#1a5e33'>✨ <b>New:</b> "
                  "open any country’s guide and tap <b>Plan with AI</b> for a tailored, month-aware "
                  "itinerary — ChatGPT or Claude, your call.</div>")
    gems_block = ""
    if gems:
        gems_block = ("<h2 style='font-size:18px;margin:20px 0 4px;color:#111'>\U0001f48e Hidden gems</h2>"
                      "<p style='font-size:13px;color:#555;margin:0 0 12px'>Under-the-radar, high-value "
                      "spots the crowds miss:</p>" + "".join(_gem_line(s, m) for s in gems))

    body = """<div style="display:none;font-size:1px;color:#f4f5f6;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden">%s&#847;&#847;&#847;&#847;&#847;&#847;&#847;&#847;&#847;&#847;</div>
<div style="max-width:600px;margin:0 auto;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#111;background:#f4f5f6;padding:20px">
  <div style="text-align:center;margin:0 0 18px">
    <div style="font-size:22px;font-weight:800;color:#111">\U0001f30d WanderGrade</div>
    <div style="font-size:14px;color:#555">Where Should I Travel Next?</div>
  </div>
  <p style="font-size:15px;line-height:1.5;color:#111">Where’s worth it in <b>%s %s</b>? WanderGrade grades every country <b>A+ to F</b> on what your trip actually hinges on — how far your money goes, safety, weather and flights. The twist: we flag where <b>your dollar is unusually strong right now</b>. This month’s standouts \U0001f447</p>
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
    Grades are for a US traveler planning %s travel; set your home country on the site to re-grade for you. Currency data as of %s. Photos via Wikimedia Commons.<br>
    <b>WanderGrade</b> · once a month, no spam · <a href="%s" style="color:#888">wandergrade.com</a> · <a href="%s" style="color:#888">unsubscribe</a>
  </p>
</div>""" % (_esc(preheader), _esc(mn), yr, _esc(mn), SITE, GREEN, hero, rest, ai_callout,
             gems_block, month_link, GREEN, _quote_for(yr, m),
             _esc(mn), _esc(data["as_of"]), SITE, UNSUB)

    return subject, body
