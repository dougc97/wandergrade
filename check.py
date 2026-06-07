#!/usr/bin/env python3
"""Scheduled job: fetch rates, find favorable currencies, email a digest.

Run manually:   python3 check.py
Dry run (no email, just print):   python3 check.py --dry-run
Schedule it with cron/launchd (see README).
"""

import datetime
import sys

from fxtracker import mailer, rates, store


def _now():
    return datetime.datetime.now()


def _hours_since(iso_ts):
    try:
        then = datetime.datetime.fromisoformat(iso_ts)
    except (ValueError, TypeError):
        return float("inf")
    return (_now() - then).total_seconds() / 3600.0


def run(dry_run=False):
    cfg = store.load_config()
    state = store.load_state()
    last_alerts = state.setdefault("last_alerts", {})

    result = rates.compute_favorability(
        baseline_days=cfg["baseline_days"],
        threshold_pct=cfg["threshold_pct"],
        watch=cfg["watch"],
    )

    # Favorable AND on the watch list (empty watch list = everything).
    favorable = [r for r in result["rows"] if r["favorable"] and r["watched"]]

    # Suppress currencies alerted within the cooldown window.
    cooldown = cfg["alert_cooldown_hours"]
    fresh = [r for r in favorable if _hours_since(last_alerts.get(r["code"], "")) >= cooldown]

    print("As of {0}: {1} favorable, {2} new after cooldown.".format(
        result["as_of"], len(favorable), len(fresh)))
    for r in favorable:
        flag = "NEW" if r in fresh else "cooldown"
        print("  [{0}] {1} {2}  +{3}% vs avg".format(
            flag, r["code"], r["rate_now"], r["strength_pct"]))

    if not fresh:
        print("Nothing new to alert.")
        return 0

    if dry_run:
        print("\n--dry-run: would email but not sending.")
        return 0

    if not mailer.is_configured(cfg["email"]):
        print("\nEmail not configured (see config.json / FX_SMTP_PASSWORD). Skipping send.")
        return 1

    subject, text, html = mailer.render_alert(
        fresh, result["as_of"], result["baseline_days"])
    mailer.send_email(cfg["email"], subject, text, html)
    print("\nSent alert to {0}.".format(cfg["email"]["to_addr"]))

    stamp = _now().isoformat()
    for r in fresh:
        last_alerts[r["code"]] = stamp
    store.save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(run(dry_run="--dry-run" in sys.argv))
