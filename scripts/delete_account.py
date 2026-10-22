#!/usr/bin/env python3
"""Delete a reader's account and newsletter subscription, as /privacy promises
("email me and I'll delete it"). Owner-only; run it from a machine with the
production keys in the environment:

    UPSTASH_REDIS_REST_URL=... UPSTASH_REDIS_REST_TOKEN=... BUTTONDOWN_API_KEY=... \\
        /usr/bin/python3 scripts/delete_account.py reader@example.com          # look only
    ...                                                                       --yes  # delete

It removes, in this order (fxtracker/accounts.delete_account): every signed-in
session for the address and any unused sign-in link, the account record (the
Wander List, the newsletter choice, the dates), the address's sign-in counter,
and the Buttondown subscriber. Without --yes it only reports what is there.
Reply to the reader once it says "deleted" or "absent" for everything.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fxtracker import accounts  # noqa: E402


def main(argv):
    args = [a for a in argv if a != "--yes"]
    if len(args) != 1 or not accounts.valid_email(accounts.norm_email(args[0])):
        print(__doc__)
        return 2
    if not accounts.storage_configured():
        print("UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN aren't set: nothing to look in.")
        return 2
    go = "--yes" in argv
    r = accounts.delete_account(args[0], dry_run=not go)
    print("%s %s" % ("Deleted for" if go else "Found for (nothing deleted; add --yes)", r["email"]))
    print("  account record: %s" % ("yes" if r["user"] else "none"))
    print("  signed-in sessions: %d   unused sign-in links: %d" % (r["sessions"], r["links"]))
    print("  newsletter (Buttondown): %s" % r["newsletter"])
    return 1 if r["newsletter"].startswith("failed") else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
