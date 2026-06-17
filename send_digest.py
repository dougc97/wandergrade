#!/usr/bin/env python3
"""Monthly travel digest: score destinations the way the site does and email
the graded picks to the Buttondown newsletter list.

  python3 send_digest.py            # build + send to subscribers (needs BUTTONDOWN_API_KEY)
  python3 send_digest.py --draft    # build + save as a Buttondown DRAFT (preview / test)
  python3 send_digest.py --dry-run  # build + print the email, send nothing
  python3 send_digest.py --month 8  # feature a specific month (1-12)

Schedule monthly (GitHub Actions / cron). Distinct from check.py, which is the
currency-favorability alert to your personal inbox.
"""

import sys

from fxtracker import newsletter, picks


def run(dry_run=False, month=None, draft=False):
    data = picks.build(month=month)
    subject, body = newsletter.render_digest(data)

    print("Digest for {0} {1} (rates as of {2}): {3} picks, {4} gems.".format(
        data["month_name"], data["year"], data["as_of"],
        len(data["picks"]), len(data["gems"])))

    if dry_run:
        print("\n--- SUBJECT ---\n" + subject)
        print("\n--- BODY (markdown) ---\n" + body)
        print("\n--dry-run: nothing sent.")
        return 0

    if not newsletter.is_configured():
        print("BUTTONDOWN_API_KEY not set — cannot send. Use --dry-run to preview.")
        return 1
    try:
        newsletter.send(subject, body, draft=draft)
        if draft:
            print("Created Buttondown draft. Open it in Buttondown to preview or send a test.")
        else:
            print("Sent digest to Buttondown subscribers.")
        return 0
    except Exception as e:
        print("Buttondown send failed:", e)
        return 1


def _parse_args(argv):
    dry = "--dry-run" in argv
    draft = "--draft" in argv
    month = None
    if "--month" in argv:
        try:
            month = int(argv[argv.index("--month") + 1])
        except (ValueError, IndexError):
            print("--month needs a number 1-12")
            sys.exit(2)
    return dry, month, draft


if __name__ == "__main__":
    dry, month, draft = _parse_args(sys.argv[1:])
    sys.exit(run(dry_run=dry, month=month, draft=draft))
