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
    lines += ["", "_Sent by Wandergrade. Good time to plan a trip._"]
    return "\n".join(lines)


# ---- monthly graded-picks digest -------------------------------------------
# Renders the payload from fxtracker.picks.build() into the Buttondown email.

_FLAG = {1: "A", 2: "B", 3: "D"}   # safety grade by advisory level (picks.SAFE_GRADE)


def _grade(score):
    return ("A+" if score >= 93 else "A" if score >= 85 else "B+" if score >= 78
            else "B" if score >= 68 else "C" if score >= 55 else "D" if score >= 42
            else "F")


SITE = "https://wandergrade.com"


def _guide_url(iso, month):
    return "{0}/?tab=guide&gc={1}&vmn={2}".format(SITE, iso, month)


def _ai_url(iso, month):
    """Deep link to the site's Travel Guide for this country with the
    'Plan with AI' panel auto-opened (ai=1), month-aware via vmn. Keeps the AI
    hand-off on-site, where the prompt is richer and the reader can pick
    ChatGPT / Claude / copy."""
    return "{0}/?tab=guide&gc={1}&vmn={2}&ai=1".format(SITE, iso, month)


def _pick_card(s, month):
    g = _guide_url(s["iso"], month)
    lines = []
    if s.get("photo"):
        lines.append("[![{name}]({src})]({g})".format(
            name=s["name"], src=s["photo"], g=g))
        lines.append("")
    lines.append("### {flag} [{name}]({g}) — Overall {ov}".format(
        flag=s["flag"], name=s["name"], g=g, ov=_grade(s["value"])))
    lines.append("💰 Affordability **{a}**  ·  🛡️ Safety **{sf}**  ·  🌤️ Weather **{w}**".format(
        a=_grade(s["afford"]), sf=_FLAG.get(s["advLvl"], "B"), w=_grade(s["wx"])))
    if s.get("activities"):
        lines.append("**Don't miss:** " + ", ".join(s["activities"]))
    lines.append("📖 [Travel guide]({g})  ·  ✨ [Plan with AI]({ai})".format(
        g=g, ai=_ai_url(s["iso"], month)))
    return "\n".join(lines)


def _gem_line(s, month):
    return ("{flag} **[{name}]({g})** — **{ov}**  ·  💰 {a} · 🛡️ {sf} · 🌤️ {w}  "
            "·  [guide]({g}) · [plan with AI]({ai})").format(
        flag=s["flag"], name=s["name"], g=_guide_url(s["iso"], month), ov=_grade(s["value"]),
        a=_grade(s["afford"]), sf=_FLAG.get(s["advLvl"], "B"), w=_grade(s["wx"]),
        ai=_ai_url(s["iso"], month))


def render_digest(data):
    """Return (subject, markdown_body) for the monthly graded-picks email."""
    mn, yr = data["month_name"], data["year"]
    month_link = "{0}/?vmn={1}".format(SITE, data["month"])
    subject = "🧭 {0}'s best-value trips, graded A+ to F".format(mn)

    out = [
        "Where's worth it in **{0} {1}**? Wandergrade grades every country "
        "**A+ to F** on what your trip actually hinges on — how far your money "
        "goes, safety, and weather. This month's standouts:".format(mn, yr),
        "",
        "## 🌟 Top picks",
        "",
        "\n\n".join(_pick_card(s, data["month"]) for s in data["picks"]),
    ]

    if data["gems"]:
        out += [
            "",
            "## 💎 Hidden gems",
            "Less-touristed, high-value spots the crowds tend to miss:",
            "",
            "\n\n".join(_gem_line(s, data["month"]) for s in data["gems"]),
        ]

    out += [
        "",
        "---",
        "",
        "**[See every country's grades & build your own ranking →]({0})**".format(month_link),
        "",
        "_Grades are for a US traveler planning {0} travel. On the site you can "
        "set your home country and weight what matters most to you — budget, "
        "safety, weather, or cheap flights (graded live there). Currency data "
        "as of {1}._".format(mn, data["as_of"]),
    ]
    return subject, "\n".join(out)
