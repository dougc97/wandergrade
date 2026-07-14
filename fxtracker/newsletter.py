"""Send the monthly digest to a Buttondown newsletter list (handles the
subscriber list, delivery, and unsubscribe for us). Gated on BUTTONDOWN_API_KEY.

Public signups happen via the embedded form on the site (only the public
newsletter username is needed there — no secret). This module is the other half:
pushing our generated digest to all subscribers via the Buttondown API.

render_digest() now returns a self-contained HTML email (Buttondown accepts an
HTML body and wraps it with the unsubscribe/address footer). The {{ unsubscribe_url }}
token is filled by Buttondown on send; the sample-to-self flow substitutes it.
"""

import html
import json
import os
import urllib.request

from . import rates  # reuse verifying SSL context

API = "https://api.buttondown.email/v1/emails"


def api_key():
    return os.environ.get("BUTTONDOWN_API_KEY", "")


def is_configured():
    return bool(api_key())


def send(subject, body_markdown, draft=False):
    """Create an email. draft=True saves it as a Buttondown draft (preview /
    send-test from the UI); otherwise it sends to the whole list. Raises on
    failure."""
    payload = json.dumps({
        "subject": subject,
        "body": body_markdown,
        "status": "draft" if draft else "about_to_send",
    }).encode("utf-8")
    req = urllib.request.Request(API, data=payload, method="POST", headers={
        "Authorization": "Token " + api_key(),
        "Content-Type": "application/json",
        "User-Agent": "fx-tracker/1.0",
    })
    with urllib.request.urlopen(req, timeout=30, context=rates._SSL) as resp:
        return resp.status in (200, 201)


def render_markdown(rows, as_of, baseline_days):
    lines = ["The US dollar is favorable vs its {0}-day average for:".format(baseline_days), ""]
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
    """The WanderGrade hook: the dollar is unusually strong here right now."""
    fx = s.get("fx")
    if fx is None or fx < 3:
        return ""
    pct = int(round(fx))
    if compact:
        return ("<div style='font-size:13px;color:%s;margin:4px 0 0'>\U0001f4b5 Dollar ~%d%% "
                "above its 1-yr average here</div>" % (GREEN, pct))
    return ("<div style='font-size:14px;color:%s;font-weight:600;margin:8px 0 0'>\U0001f4b5 "
            "Your dollar is about %d%% stronger here than its 1-year average — rarely this good."
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
        <div style="font-size:14px;color:#444;margin:5px 0 0">\U0001f4b0 Affordability <b>%s</b> &nbsp;&middot;&nbsp; \U0001f6e1️ Safety <b>%s</b> &nbsp;&middot;&nbsp; \U0001f324️ Weather <b>%s</b></div>
        %s%s%s
        <div style="margin:14px 0 0"><a href="%s" style="display:inline-block;background:%s;color:#fff;text-decoration:none;font-weight:700;font-size:14px;padding:10px 18px;border-radius:9px">See %s’s guide →</a></div>
      </div>
    </div>""" % (photo, _flag_img(s["iso"]), g, GREEN, _esc(s["name"]), _grade(s["value"]),
                 _grade(s["afford"]), _FLAG.get(s["advLvl"], "B"), _grade(s["wx"]),
                 _fx_line(s), _cost_line(s), _dont_miss(s), g, GREEN, _esc(s["name"]))


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
          <div style="font-size:13px;color:#555;margin:3px 0 0">\U0001f4b0 %s &middot; \U0001f6e1️ %s &middot; \U0001f324️ %s</div>
          %s
          <div style="font-size:13px;margin:6px 0 0"><a href="%s" style="color:%s;text-decoration:none;font-weight:600">See the guide →</a></div>
        </td>
      </tr>
    </table>""" % (thumb, _flag_img(s["iso"]), g, GREEN, _esc(s["name"]), _grade(s["value"]),
                   _grade(s["afford"]), _FLAG.get(s["advLvl"], "B"), _grade(s["wx"]),
                   _value_line(s, compact=True), g, GREEN)


def _gem_line(s, month):
    g = _guide_url(s["iso"], month)
    return ("<div style='font-size:14px;margin:0 0 9px;color:#111'>%s<a href='%s' "
            "style='color:%s;text-decoration:none;font-weight:700'>%s</a> "
            "<span style='color:#666'>— %s &middot; \U0001f4b0 %s &middot; \U0001f6e1️ %s "
            "&middot; \U0001f324️ %s</span></div>") % (
        _flag_img(s["iso"]), g, GREEN, _esc(s["name"]), _grade(s["value"]),
        _grade(s["afford"]), _FLAG.get(s["advLvl"], "B"), _grade(s["wx"]))


def render_digest(data):
    """Return (subject, html_body) for the monthly graded-picks email."""
    mn, yr, m = data["month_name"], data["year"], data["month"]
    picks, gems = data["picks"], data["gems"]
    month_link = "%s/?vmn=%s" % (SITE, m)
    nstrong = sum(1 for s in picks if (s.get("fx") or 0) >= 3)

    subject = "\U0001f9ed Where your dollar goes furthest this %s" % mn
    if nstrong:
        preheader = ("Your dollar is unusually strong vs its 1-year average in %d of this "
                     "month’s picks — here’s where it’s worth going." % nstrong)
    else:
        preheader = "%d destinations graded A+ to F on value, safety and weather this %s." % (len(picks), mn)

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
  <p style="font-size:15px;line-height:1.5;color:#111">Where’s worth it in <b>%s %s</b>? WanderGrade grades every country <b>A+ to F</b> on what your trip actually hinges on — how far your money goes, safety, and weather. The twist: we flag where <b>your dollar is unusually strong right now</b>. This month’s standouts \U0001f447</p>
  <p style="font-size:13px;color:#555;background:#eef7f0;border-radius:8px;padding:10px 12px">\U0001f4c5 Featured for <b>%s</b> — about two months out, the sweet spot for booking. Going a different time? <a href="%s" style="color:%s;font-weight:600;text-decoration:none">Pick your travel month →</a></p>
  <h2 style="font-size:18px;margin:22px 0 10px;color:#111">\U0001f31f Top picks</h2>
  %s
  %s
  %s
  %s
  <div style="text-align:center;margin:22px 0 6px">
    <a href="%s" style="display:inline-block;background:%s;color:#fff;text-decoration:none;font-weight:700;font-size:15px;padding:12px 22px;border-radius:10px">See every country’s grades →</a>
  </div>
  <p style="font-size:13px;color:#555;margin:16px 0 0">\U0001f4ac Tell me where you’re headed — write to <a href="mailto:hello@wandergrade.com" style="color:#555"><b>hello@wandergrade.com</b></a>. I read every message.</p>
  <p style="font-size:12px;color:#888;line-height:1.6;border-top:1px solid #e0e0e0;margin-top:14px;padding-top:14px">
    Grades are for a US traveler planning %s travel; set your home country on the site to re-grade for you. Currency data as of %s. Photos via Wikimedia Commons.<br>
    <b>WanderGrade</b> · once a month, no spam · <a href="%s" style="color:#888">wandergrade.com</a> · <a href="%s" style="color:#888">unsubscribe</a>
  </p>
</div>""" % (_esc(preheader), _esc(mn), yr, _esc(mn), SITE, GREEN, hero, rest, ai_callout,
             gems_block, month_link, GREEN, _esc(mn), _esc(data["as_of"]), SITE, UNSUB)

    return subject, body
