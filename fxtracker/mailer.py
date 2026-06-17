"""Send alert emails via SMTP (stdlib smtplib). Designed for Gmail App Passwords
but works with any SMTP host that supports STARTTLS."""

import os
import smtplib
from email.message import EmailMessage


def _password(email_cfg):
    # Env var wins so you never have to commit a password to config.json.
    return os.environ.get("FX_SMTP_PASSWORD") or email_cfg.get("password", "")


def is_configured(email_cfg):
    return bool(
        email_cfg.get("enabled")
        and email_cfg.get("smtp_host")
        and email_cfg.get("username")
        and _password(email_cfg)
        and (email_cfg.get("from_addr") or email_cfg.get("username"))
        and email_cfg.get("to_addr")
    )


def send_email(email_cfg, subject, body_text, body_html=None):
    """Send one message. Raises on failure so callers can report it."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = email_cfg.get("from_addr") or email_cfg["username"]
    msg["To"] = email_cfg["to_addr"]
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    host = email_cfg["smtp_host"]
    port = int(email_cfg.get("smtp_port", 587))
    with smtplib.SMTP(host, port, timeout=30) as s:
        s.starttls()
        s.login(email_cfg["username"], _password(email_cfg))
        s.send_message(msg)


def render_alert(favorable_rows, as_of, baseline_days):
    """Build (subject, text, html) for a digest of favorable currencies."""
    n = len(favorable_rows)
    subject = "USD travel alert: {0} favorable currenc{1} ({2})".format(
        n, "y" if n == 1 else "ies", as_of
    )

    lines = [
        "The US dollar is favorable vs its {0}-day average for:".format(baseline_days),
        "",
    ]
    for r in favorable_rows:
        lines.append(
            "  {code} ({name}): 1 USD = {rate} {code}  |  +{pct}% vs avg  |  "
            "{pctile}th percentile".format(
                code=r["code"], name=r["name"], rate=r["rate_now"],
                pct=r["strength_pct"], pctile=int(r["percentile"]),
            )
        )
    lines += ["", "Good time to book a trip. — Wandergrade"]
    text = "\n".join(lines)

    rows_html = "".join(
        "<tr><td><b>{code}</b></td><td>{name}</td>"
        "<td style='text-align:right'>{rate}</td>"
        "<td style='text-align:right;color:#0a7d28'><b>+{pct}%</b></td>"
        "<td style='text-align:right'>{pctile}th</td></tr>".format(
            code=r["code"], name=r["name"], rate=r["rate_now"],
            pct=r["strength_pct"], pctile=int(r["percentile"]),
        )
        for r in favorable_rows
    )
    html = """\
<div style="font-family:system-ui,Arial,sans-serif">
  <h2>USD is favorable for travel ({as_of})</h2>
  <p>Stronger than its {days}-day average for {n} currenc{plural}:</p>
  <table cellpadding="6" style="border-collapse:collapse;font-size:14px">
    <tr style="background:#f0f0f0"><th align="left">Code</th><th align="left">Currency</th>
    <th align="right">1 USD =</th><th align="right">vs avg</th><th align="right">Range pct</th></tr>
    {rows}
  </table>
  <p style="color:#666;font-size:12px">Sent by Wandergrade. Rates from fxratesapi.com.</p>
</div>""".format(as_of=as_of, days=baseline_days, n=n,
                 plural="y" if n == 1 else "ies", rows=rows_html)

    return subject, text, html
