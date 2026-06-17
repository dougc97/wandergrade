"""Send the monthly digest to a Buttondown newsletter list (handles the
subscriber list, delivery, and unsubscribe for us). Gated on BUTTONDOWN_API_KEY.

Public signups happen via the embedded form on the site (only the public
newsletter username is needed there — no secret). This module is the other half:
pushing our generated digest to all subscribers via the Buttondown API.
"""

import json
import os
import urllib.request

from . import rates  # reuse verifying SSL context

API = "https://api.buttondown.email/v1/emails"


def api_key():
    return os.environ.get("BUTTONDOWN_API_KEY", "")


def is_configured():
    return bool(api_key())


def send(subject, body_markdown):
    """Create + send an email to the whole list. Raises on failure."""
    payload = json.dumps({
        "subject": subject,
        "body": body_markdown,
        "status": "about_to_send",   # send now (vs "draft")
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
    lines += ["", "_Sent by Wandergrade. Good time to plan a trip._"]
    return "\n".join(lines)


# ---- monthly graded-picks digest -------------------------------------------
# Renders the payload from fxtracker.picks.build() into the Buttondown email.

_FLAG = {1: "A", 2: "B", 3: "D"}   # safety grade by advisory level (picks.SAFE_GRADE)


def _grade(score):
    return ("A+" if score >= 93 else "A" if score >= 85 else "B+" if score >= 78
            else "B" if score >= 68 else "C" if score >= 55 else "D" if score >= 42
            else "F")


def _reason(s, month_name):
    bits = []
    if s["afford"] >= 88:
        bits.append("your money goes a long way")
    elif s["afford"] >= 68:
        bits.append("good value on the ground")
    if s["wx"] >= 85:
        bits.append("superb weather in " + month_name)
    elif s["wx"] >= 68:
        bits.append("pleasant weather in " + month_name)
    if s["advLvl"] == 1 and len(bits) < 2:
        bits.append("the safest travel rating")
    phrase = ", and ".join(bits[:2]) if bits else "a solid all-round pick"
    return phrase[0].upper() + phrase[1:] + "."


def _pick_block(i, s, month_name):
    safe_g = _FLAG.get(s["advLvl"], "B")
    return (
        "**{i}. {name} — {overall}**\n"
        "💰 Affordability {a} · 🛡️ Safety {sf} · 🌤️ Weather {w}\n"
        "*{why}*"
    ).format(i=i, name=s["name"], overall=_grade(s["value"]),
             a=_grade(s["afford"]), sf=safe_g, w=_grade(s["wx"]),
             why=_reason(s, month_name))


def render_digest(data):
    """Return (subject, markdown_body) for the monthly graded-picks email."""
    mn, yr = data["month_name"], data["year"]
    link = "https://wandergrade.com/?vmn={0}".format(data["month"])
    subject = "🧭 {0}'s best-value trips, graded A+ to F".format(mn)

    out = [
        "Wandergrade grades every country **A+ to F** on what actually matters "
        "for a trip — how far your money goes, safety, and weather. Here's "
        "where the numbers point for **{0} {1}**.".format(mn, yr),
        "",
        "## 🌟 Top picks for {0}".format(mn),
        "",
    ]
    out += ["\n\n".join(_pick_block(i + 1, s, mn) for i, s in enumerate(data["picks"]))]

    if data["gems"]:
        out += ["", "## 💎 Hidden gems",
                "Less-touristed, high-value spots the crowds tend to miss:", ""]
        gem_lines = []
        for s in data["gems"]:
            gem_lines.append("**{name} — {overall}** · 💰 {a} · 🛡️ {sf} · 🌤️ {w}".format(
                name=s["name"], overall=_grade(s["value"]), a=_grade(s["afford"]),
                sf=_FLAG.get(s["advLvl"], "B"), w=_grade(s["wx"])))
        out += ["\n\n".join(gem_lines)]

    out += [
        "",
        "---",
        "",
        "**[See every grade and build your own ranking →]({0})**".format(link),
        "",
        "_Grades shown are for a US traveler planning {0} travel — on the site "
        "you can set your home country and weight what you care about most "
        "(budget, safety, weather, flights). Flight deals are graded live there "
        "too. Currency data as of {1}._".format(mn, data["as_of"]),
    ]
    return subject, "\n".join(out)
