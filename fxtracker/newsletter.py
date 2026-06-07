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
    lines += ["", "_Sent by fx-tracker. Good time to plan a trip._"]
    return "\n".join(lines)
